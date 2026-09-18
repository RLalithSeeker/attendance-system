# Minimum reproducible test matrix

| ID | Scenario | Expected |
|---|---|---|
| A01 | No face | No attendance |
| A02 | Face detected, no matcher | Disabled/review-only, never marked |
| A03 | Unenrolled face | Unknown, no mark |
| A04 | Ambiguous match | Review only |
| A05 | Matched but no consent | No mark |
| A06 | Matched but not on roster | No mark |
| A07 | Matched on active session | One mark |
| A08 | Repeat/concurrent frames | One DB attendance row |
| A09 | Session closed | No mark |
| A10 | Different teacher's class | 403, no export |
| A11 | Manual correction without reason | Validation failure |
| A12 | Revoked/deleted template | No future recognition |
| A13 | Invalid or huge upload | Reject safely |
| A14 | CSV formula payload | Escaped appropriately |
| A15 | Demo mode in production config | Refuse startup or disable simulated matching |
| A16 | Real consented photo replay | Record as known residual risk; never claim prevention without actual validated liveness |

Record exact implementation test filenames and results during build. Mock tests cannot substitute for real camera/accuracy evaluation.
