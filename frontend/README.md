# Next.js Frontend

This folder contains the React + Next.js frontend migration for the dynasty trade calculator.

## Run

```powershell
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## Data source

The frontend reads your latest scraper output through:

- `GET /api/dynasty-data`

The API route looks for, in order:

1. newest `dynasty_data_YYYY-MM-DD.json` in `../data/`
2. newest `dynasty_data_YYYY-MM-DD.json` in `../`
3. `../dynasty_data.js` or `../data/dynasty_data.js`
