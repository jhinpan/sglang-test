# SGLang Concurrency Test Results Summary

## Visual Performance Comparison

```
Success Rate by Concurrency Level:

100% |████████████████████████████████████████████████ Direct Worker
     |                                         ██
 80% |                                           ██
 60% |                                             ██
     |________________________________________________
      10   20   50  100  200  500  1k  2k  5k 10k 20k 30k 40k 50k

100% |████████████████████████████████████████████████████ Router (2 workers)
     |                                                   ██
 80% |                                                     ██
     |________________________________________________
      10   20   50  100  200  500  1k  2k  5k 10k 20k 30k 40k 50k

100% |████████████████████████████████████████████████████████ Router (4 workers)  
     |                                                       ████
 80% |                                                           ██
     |________________________________________________
      10   20   50  100  200  500  1k  2k  5k 10k 20k 30k 40k 50k
```

## Key Metrics at Critical Thresholds

### At 30,000 Concurrent Connections
- **Direct Worker**: 100% success, 0.060 req/s
- **Router (2 workers)**: 100% success, 0.077 req/s
- **Router (4 workers)**: 100% success, 0.084 req/s
- **Observation**: All modes handle 30k, but router has 28-40% better throughput

### At 40,000 Concurrent Connections
- **Direct Worker**: 74.2% success (10,314 failures)
- **Router (2 workers)**: 97.5% success (990 failures)
- **Router (4 workers)**: 100% success (0 failures)
- **Observation**: Router with 4 workers maintains perfect reliability

### At 50,000 Concurrent Connections
- **Direct Worker**: 58.8% success (20,605 failures)
- **Router (2 workers)**: 78.8% success (10,607 failures)
- **Router (4 workers)**: 89.8% success (5,111 failures)
- **Observation**: All modes degraded, but router performs 34-53% better

## Latency Progression

### Average Latency Growth
```
Concurrency  Direct    Router-2w  Router-4w
10           0.050s    0.041s     0.040s
100          0.116s    0.150s     0.125s
1,000        0.564s    0.467s     0.356s
10,000       5.812s    4.267s     3.664s
30,000       16.672s   13.041s    11.925s
40,000       17.478s   17.250s    15.142s
50,000       18.753s   17.867s    17.157s
```

## Throughput Comparison

### Requests per Second
```
Concurrency  Direct    Router-2w  Router-4w  Improvement
10           19.9      24.3       25.1       +26%
100          8.6       6.7        8.0        -7%
1,000        1.8       2.1        2.8        +56%
10,000       0.17      0.23       0.27       +59%
30,000       0.060     0.077      0.084      +40%
```

## Failure Analysis

### When Failures Begin
- **Direct Worker**: First failures at 30k (system at 32,768 limit)
- **Router (2 workers)**: First failures at 40k (load distributed)
- **Router (4 workers)**: First failures at 50k (maximum distribution)

### Failure Rate at 50k Connections
- **Direct Worker**: 41.2% failure rate
- **Router (2 workers)**: 21.2% failure rate
- **Router (4 workers)**: 10.2% failure rate

## Conclusions

1. **Router provides significant benefits** for high-concurrency scenarios
2. **32,768 connection limit** is clearly visible across all tests
3. **More workers = better resilience** but doesn't eliminate the fundamental limit
4. **Router with 4 workers** is optimal for extreme concurrency
5. **All configurations need proper connection management** above 30k concurrent requests