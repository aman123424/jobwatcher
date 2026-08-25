from fetchers import fetch_workday
jobs = fetch_workday('APTIV', 'aptiv|wd5|aptiv_careers')
print(f'Collected {len(jobs)} jobs (page 1 said total=731)')