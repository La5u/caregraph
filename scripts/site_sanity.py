"""Bounded, offline publication checks. No clinician dictionary, fuzzy matching or geocoding.

The former audit materialized all graph records, all owner rows, a million-clinician name dictionary,
and deletion indexes for fuzzy spelling suggestions. Those identity checks are obsolete for tokens.
This audit streams one shard at a time and projects only distinct identity columns from CMS.
Usage: .venv/bin/python -I scripts/site_sanity.py
"""
import json
import re
import runpy
import time
from collections import Counter, defaultdict
from pathlib import Path

import duckdb


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def check_site(root):
    started = time.monotonic()
    built = root / 'site/dist'
    helpers = runpy.run_path(str(root / 'scripts/site_tables.py'))
    words = helpers['words']
    db = duckdb.connect(str(root / 'data/fraud.duckdb'), read_only=True)
    db.execute("SET threads=2; SET memory_limit='384MB'")
    names, ids, orgs, individual_orgs = helpers['owner_identities'](db)
    # Full public business names, never a blanket exception for the contained person's name.
    public_names = {n for n in orgs if not helpers['person_like'](n, names, individual_orgs)}
    public_numbers = set()
    for table in ('hist_hospice_enrollments', 'hist_hha_enrollments', 'hospice_enrollments', 'hha_enrollments'):
        # Addresses and cities count as public place names: streets and towns are often named after people (VANCE JACKSON RD).
        cur = db.execute(f'SELECT DISTINCT "ORGANIZATION NAME", "DOING BUSINESS AS NAME", "ENROLLMENT ID", CCN, NPI, "ADDRESS LINE 1", "ADDRESS LINE 2", CITY FROM {table}')
        while batch := cur.fetchmany(8192):
            for name, dba, eid, ccn, npi, a1, a2, city in batch:
                public_names.update(n for n in (name, dba, a1, a2, city) if n)
                public_numbers.update(str(n) for n in (eid, ccn, npi) if n)
    db.close()
    allowed = defaultdict(set)
    for name in public_names:
        tokens = tuple(words(name))
        if len(tokens) >= 2 and helpers['contains_name'](name, names):
            allowed[tokens[:2]].add(tokens)
    print('Allowlist: public business, street and city names containing owner names:', sum(map(len, allowed.values())))
    print('Allowlist: public identifiers overlapping individual associate IDs:', len(public_numbers & ids))
    exempt, failures = Counter(), Counter()
    STREET_TYPES = set("RD ROAD ST STREET DR DRIVE HWY HIGHWAY BLVD AVE AVENUE PKWY PARKWAY LN LANE CT PL WAY CIR TRL FWY SQ TER EXPY LOOP MARIN".split())
    def scan(value, filename):
        tokens = words(value)
        covered = set()
        for i in range(len(tokens) - 1):
            for candidate in allowed.get(tuple(tokens[i:i + 2]), ()):
                if tuple(tokens[i:i + len(candidate)]) == candidate:
                    covered.update(range(i, i + len(candidate)))
                    exempt['business name occurrences'] += 1
        for i in range(len(tokens) - 1):
            for candidate in names.get(tuple(tokens[i:i + 2]), ()):
                if tuple(tokens[i:i + len(candidate)]) == candidate and not all(j in covered for j in range(i, i + len(candidate))):
                    after = tokens[i + len(candidate)] if i + len(candidate) < len(tokens) else ""
                    before = tokens[i - 1] if i else ""
                    if after in STREET_TYPES or before in ("CALLE", "AVENIDA", "AVE", "CARR", "PASEO", "CAMINO"):   # a street named after a person (address keys are normalized, so not in the allowlist)
                        exempt['street name occurrences'] += 1
                        continue
                    failures[filename + ': person name'] += 1
        for token in tokens:
            numeric = re.fullmatch(r'[PO]?(0*\d+)', token)
            if numeric and (numeric[1] in ids or numeric[1].lstrip('0') in ids):
                if token in public_numbers:
                    exempt['public identifier occurrences'] += 1
                else:
                    failures[filename + ': individual associate ID'] += 1
        if re.search(r'\bFELON|EXCLU(?:DED|SION) FROM (?:MEDICARE|MEDICAID|FEDERAL|PARTICIPATION)|\bDEBARR|SUSPEN(?:DED|SION) FROM (?:MEDICARE|MEDICAID|FEDERAL|PARTICIPATION)|\bCONVICT|\(a\)\s*\(0?[23]\)', value, re.I):
            failures[filename + ': restricted ground text'] += 1
    html = (built / 'index.html').read_text()
    match = re.search(r'const DATA = "data/([a-f0-9]{20})/"', html)
    assert match, 'Missing content-versioned data path; rebuild the site'
    assert '__VERSION__' not in html
    dist = built / 'data' / match[1]
    index = json.loads((dist / 'index.json').read_text())
    assert all('people' not in g and 's' not in g for g in index['groups'])
    search = json.loads((dist / 'search.json').read_text())
    assert set(search) == {str(g['id']) for g in index['groups']}
    paths = json.loads((dist / 'path-edges.json').read_text())
    assert 's' not in paths['cat'], 'Same-name path edge published'
    del paths, search
    assert 'immutable' in (built / '_headers').read_text()
    assert 'X-Robots-Tag: noindex, nofollow, noarchive' in (built / '_headers').read_text()
    for tag in re.findall(r'<script src="([^"]+)"', html):
        assert match[1] in tag and (built / tag).is_file(), 'Missing versioned JS: ' + tag
    agencies = json.loads((dist / 'agencies.json').read_text())
    assert len({n['id'] for n in agencies}) == len(agencies), 'Duplicate agency enrollment'
    assert json.loads((dist / 'agencies-first.json').read_text()) == agencies[:100]
    assert all(n.get('kind') == 'hospice' or not n.get('ind') for n in agencies)
    forbidden = {'carrier', 'leie_name_match', 'official_phone', 'official', 'official_title', 'risk_score',
                 'bene_avg_risk_scre', 'cms_id', 'listed_names', 'merged_ids', 'same_name', 'same_name_ids', 'middle', 'title'}
    suppressed = helpers['suppressions'](root / 'data/suppress.txt')
    def check_node(n):
        assert not forbidden.intersection(n), 'Private field in published node'
        assert n['id'] not in suppressed and n.get('ccn') not in suppressed, 'Suppressed node published'
        if n['kind'] == 'person' or n.get('name', '').startswith('Entity '):
            assert re.fullmatch(r'[A-Z2-7]{16}', n['id']), 'Non-token identity'
            assert n['name'] == ('Person ' if n['kind'] == 'person' else 'Entity ') + n['id']
            assert n['name'] not in suppressed
        if n['kind'] not in ('hospice', 'hha'):
            assert not {'ind', 'ind_na', 'm', 'na'}.intersection(n), 'Agency measures on non-agency'   # x/y are layout coordinates
        if n.get('ccn'):
            assert re.fullmatch(r'[0-9A-Z]{6,7}', n['ccn']), 'Invalid CCN'
        if n.get('first_seen') and n.get('last_seen'):
            assert n['first_seen'] <= n['last_seen'], 'Reversed release dates'
        if isinstance(n.get('paid'), (int, float)):
            assert n['paid'] >= 0, 'Negative payment'
    for n in agencies:
        check_node(n)
    metrics = json.loads((dist / 'metrics.json').read_text())
    assert all(r.get('k') != 'hha' or not any(k in r for k in ('ind', 'ind_na', 'bldg_n')) for r in metrics.values())
    assert set(metrics) <= {n.get('ccn') for n in agencies}
    del metrics, agencies
    counts = Counter()
    files = [f for f in built.rglob('*') if f.is_file()]
    assert len(files) < 20_000, 'Cloudflare file limit'
    for f in files:
        assert time.monotonic() - started < 175, 'Publication check exceeded 175 seconds'
        assert f.stat().st_size <= 25 * 1024 * 1024, 'Cloudflare size limit: ' + str(f)
        filename = str(f.relative_to(built))
        if f.suffix == '.json':
            value = json.loads(f.read_text())
            for text in strings(value):
                scan(text, filename)
            if f.parent == dist / 'g':
                records = json.loads((dist / 'r' / f.name).read_text())
                for gid, graph in value.items():
                    rs = records[gid]
                    assert len(rs) == len(graph['edges']), 'Record alignment'
                    byid = {n['id']: n for n in graph['nodes']}
                    for n in graph['nodes']:
                        check_node(n)
                    for e, recs in zip(graph['edges'], rs):
                        assert e['from'] in byid and e['to'] in byid
                        assert e['cat'] != 'samename' and 'recs' not in e
                        assert e['fs'] == sorted({i for r in recs for i in r['f']}), 'Release membership'
                        for r in recs:
                            assert set(r) <= {'f', 'role', 'code', 'pct', 'assoc', 'addr'}, 'Private record field'
                            if r.get('pct'):
                                assert 0 <= float(r['pct']) <= 100, 'Ownership percentage'
                    counts['nodes'] += len(byid); counts['links'] += len(graph['edges'])
        else:
            text = f.read_text()
            scan(re.sub(r'<[^>]+>', ' ', text) if f.suffix == '.html' else text, filename)
        counts['bytes'] += f.stat().st_size
    report = [f'# Site publication check', str(dict(counts)), f'Allowlist occurrences: {dict(exempt)}',
              f'Publication failures: {sum(failures.values())}']
    report += [f'- {key}: {count}' for key, count in failures.items()]
    report.append(f'Elapsed: {time.monotonic() - started:.1f}s; files: {len(files)}')
    (root / 'out/site_sanity.md').write_text('\n'.join(report) + '\n')
    print('\n'.join(report))
    if failures:
        raise SystemExit('Publication check FAILED; see out/site_sanity.md')


if __name__ == '__main__':
    check_site(Path(__file__).resolve().parent.parent)
