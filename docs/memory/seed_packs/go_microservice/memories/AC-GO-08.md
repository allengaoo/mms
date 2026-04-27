---
id: AC-GO-08
layer: DOMAIN
tier: warm
type: lesson
language: go
pack: go_microservice
about_concepts: [sync-map, rwmutex, concurrency, performance, go]
cites_files: []
created_at: "2026-04-27"
---

# sync.Map 适合读多写少；写多读少用带 RWMutex 的普通 map

## 教训（Lesson）

`sync.Map` 内部使用了两个 map（read map 和 dirty map）的设计，写操作需要获取全局锁并可能触发 dirty → read 的晋升，在**写多读少**场景下性能反而不如带 `sync.RWMutex` 的普通 map。

```go
// 场景：高频写入的计数器 → sync.Map 性能差
var counters sync.Map
func increment(key string) {
    val, _ := counters.LoadOrStore(key, 0)
    counters.Store(key, val.(int)+1)   // 高频写，sync.Map 竞争严重
}

// ✅ 正确：写多读少用 RWMutex + map
type Counter struct {
    mu   sync.RWMutex
    data map[string]int
}

func (c *Counter) Increment(key string) {
    c.mu.Lock()
    defer c.mu.Unlock()
    c.data[key]++
}

func (c *Counter) Get(key string) int {
    c.mu.RLock()
    defer c.mu.RUnlock()
    return c.data[key]
}
```

## 选择指南

| 场景 | 推荐方案 |
|---|---|
| 读多写少（如配置缓存，写一次读千次） | `sync.Map` |
| 写多读少（如计数器、事件记录） | `sync.RWMutex + map` |
| 频繁读写均衡 | 根据 benchmark 决定 |
| 需要范围查询/迭代 | `sync.RWMutex + map`（sync.Map.Range 不保证顺序） |

## Benchmark 命令

```bash
go test -bench=BenchmarkSyncMap -benchmem ./...
go test -bench=BenchmarkRWMutexMap -benchmem ./...
```

## 参考

- Go 文档：[sync.Map](https://pkg.go.dev/sync#Map)
- Uber Go Style Guide：[Preferring sync/atomic Over Mutexes for Simple Types](https://github.com/uber-go/guide/blob/master/style.md)
