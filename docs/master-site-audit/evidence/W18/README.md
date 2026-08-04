# Raw contract dumps are intentionally not committed

`api_data_app.json`, `api_data_dynasty_main.json` and `api_data_dynasty_new.json`
(5.8 MB each) were captured here during the audit and are excluded from git —
they are byte-reproducible from the running stack:

    SECRET=$(cat <scratchpad>/e2e_secret.txt)
    curl -s -c /tmp/c.txt -X POST http://127.0.0.1:8000/api/test/create-session \
      -H "Authorization: Bearer $SECRET"
    curl -s -b /tmp/c.txt "http://127.0.0.1:8000/api/data?view=app" -o api_data_app.json
    curl -s -b /tmp/c.txt "http://127.0.0.1:8000/api/data?view=app&leagueKey=dynasty_main" \
      -o api_data_dynasty_main.json
    curl -s -b /tmp/c.txt "http://127.0.0.1:8000/api/data?view=app&leagueKey=dynasty_new" \
      -o api_data_dynasty_new.json

The derived comparison artifacts in this directory ARE committed — they are the
audit evidence; the raw inputs are just large.
