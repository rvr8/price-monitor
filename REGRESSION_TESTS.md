# Regression Tests — E2E

Run after every feature release.

| # | Test | Steps |
|---|------|-------|
| **1** | **Search + Track** | Search "Cybex Balios" → verify results from multiple retailers → click Track → verify product on dashboard |
| **2** | **Search Anex Flo** | Search "Anex Flo" → verify BabyMatters returns results (was previously broken) |
| **3** | **Product page** | Open tracked product → verify price chart, Where to Buy, frequency selector loads |
| **4** | **Change frequency** | Click "Every 24h" → reload page → verify it persists |
| **5** | **Archive + Restore** | Archive product → verify gone from dashboard → go to Archive page → click Restore → verify back on dashboard |
| **6** | **Delete** | Track a throwaway product → Delete it → verify gone from dashboard + archive |
| **7** | **Mobile layout** | Check dashboard, product page, retailers page at 375px width |
