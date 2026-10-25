# Live runs: time and AI requests as measured (the *_after.json files were re-scored later from recorded answers)
## gemini before (26.10.2026 00:28, all rows live)
s1_slang requests 1 seconds 121.8 ai_rows 153
s2_typos requests 3 seconds 68.5 ai_rows 44
s3_columns requests 0 seconds 0.2 ai_rows 0
s4_merged requests 4 seconds 118.2 ai_rows 81
s5_multitable requests 0 seconds 0.2 ai_rows 0
s6_csv_cp1251 requests 2 seconds 13.6 ai_rows 4
s7_pdf requests 0 seconds 1.0 ai_rows 0
gshop requests 3 seconds 92.2 ai_rows 166
posts requests 3 seconds 41.3 ai_rows 31
{'config': 'gemini', 'tag': 'before', 'live_requests': 16, 'replayed_rows': 0, 'not_recorded_rows': 0, 'seconds': 458.8, 'date': '2026-10-26 00:28'}
## groq after (01:09, all AI rows live)
=== groq ===
dataset          rows found category    brand    model    price currency conditio     card   specs  traps  falseF  extra req   sec
s1_slang          155   155     98.7     94.8     98.0    100.0    100.0    100.0     65.3   65.0   7/7    1/148     0   5  94.9
s2_typos          154   154    100.0     95.5     91.3    100.0    100.0    100.0     79.3   95.9   6/6    1/148     0   6 136.1
s3_columns        150   150    100.0    100.0    100.0    100.0    100.0    100.0     99.3   99.7   0/0    0/150     0   0   0.3
s4_merged         150   150    100.0    100.0    100.0    100.0    100.0    100.0     63.3   99.8   2/2    0/148     0   8 215.9
s5_multitable     150   150    100.0    100.0    100.0    100.0    100.0    100.0    100.0   99.8   1/1    0/149     0   0   0.3
s6_csv_cp1251     154   154    100.0    100.0    100.0    100.0    100.0    100.0     99.3  100.0   5/5    0/149     0   1   2.0
s7_pdf            150   150    100.0    100.0    100.0    100.0    100.0    100.0    100.0   99.8   1/1    0/149     0   0   0.7
gshop              70    69     97.1     95.7     92.9     98.6     98.6     98.6        -   93.2   0/0    0/69     14   8 204.8
posts              31    31    100.0     96.8     96.3    100.0    100.0    100.0        -  100.0   0/0    1/31      0   2  26.7
{'config': 'groq', 'tag': 'after', 'live_requests': 30, 'replayed_rows': 0, 'not_recorded_rows': 0, 'seconds': 683.3, 'date': '2026-10-26 01:09'}
## gemini after: only changed rows live — s4 1 req 16.5 s, gshop 2 req 24.7 s, posts 2 req 21.1 s; re-ask of 32 skipped rows with the fixed prompt: 1 req
