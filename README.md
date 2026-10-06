# NHL Prediction Capstone

## Getting Started

### Build and Run Locally

1. Create a `.env` file from the provided `.env.example`.
2. Fill in the required environment variables.
3. Build and start the containers:

```bash
docker compose up --build
```

### Refreshing Data Manually

The backend refreshes data on startup and nightly at 03:00. To trigger a full refresh (teams, schedules, rosters,
game logs, features, live scores, player props and model training) on demand, set `ADMIN_TOKEN` in `.env` and call:

```bash
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8002/admin/refresh
```

The refresh runs in the background and returns `202` immediately, or `409` if a refresh is already running.
Check its progress with:

```bash
curl -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8002/admin/refresh
```

Both endpoints can also be called from the API docs at http://localhost:8002/docs: click **Authorize**, enter the token,
then use **Try it out** on the `admin` endpoints.
## 📊 Data Sources & Attribution

This project relies on data provided by **Moneypuck** and the **NHL**. Without their comprehensive data collection and advanced modeling, this predictive analysis would not be possible.

### [Moneypuck](https://moneypuck.com)
The core of this model’s predictive power comes from Moneypuck’s advanced player-game-level data.

### [NHL API](https://www.nhl.com/)
Raw team metadata and statistics are sourced from the official NHL API.

---

> **Disclaimer:** This project is an independent analysis and is not affiliated with, endorsed by, or sponsored by the National Hockey League (NHL) or Moneypuck.com. All NHL logos and marks are the property of the NHL.