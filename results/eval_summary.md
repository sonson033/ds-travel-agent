| Case | Expected | Agent | Correct | Plan valid | Price | Tool calls | Turns | Tool failures |
|---|---|---|---|---|---|---|---|---|
| R01 | PLAN | PLAN | yes | yes | 351 EUR | 27 | 1 | {'timeout': 5} |
| R02 | PLAN | PLAN | yes | yes | 492 EUR | 31 | 1 | {'timeout': 5} |
| R03 | PLAN | PLAN | yes | yes | 634 EUR | 27 | 1 | {'timeout': 5} |
| R04 | ASK | ASK | yes | - | - | 0 | 1 | - |
| R05 | ASK | ASK | yes | - | - | 0 | 1 | - |
| R06 | ASK | ASK | yes | - | - | 0 | 1 | - |
| R07 | ASK | ASK | yes | - | - | 0 | 1 | - |
| R08 | DECLINE | DECLINE | yes | - | - | 8 | 1 | {'timeout': 1} |
| R09 | PLAN | PLAN | yes | yes | 436 EUR | 27 | 1 | {'timeout': 5} |
| R10 | DECLINE | DECLINE | yes | - | 289 EUR | 18 | 1 | {'timeout': 2} |
| D1 | ASK | DECLINE | yes | - | - | 34 | 2 | {'timeout': 5} |
| D2 | PLAN | PLAN | yes | yes | 492 EUR | 62 | 2 | {'timeout': 10} |
| D3 | PLAN | PLAN | yes | yes | 492 EUR | 62 | 2 | {'timeout': 10} |
| D4 | PLAN | PLAN | yes | yes | 664 EUR | 51 | 2 | {'timeout': 8} |
| D5 | ASK | DECLINE | yes | - | 498 EUR | 48 | 2 | {'timeout': 8} |

- **correct reaction:** 15/15
- **plan validity rate:** 7/7 plans valid
- **avg tool calls per plan:** 41.0
- **avg turns (user effort):** 1.33
- **tool failures (all cases):** {'timeout': 64}
- **cases with unrecovered failures:** []
- **avg seconds per case:** 6.6
