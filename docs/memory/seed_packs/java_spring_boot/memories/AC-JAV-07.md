---
id: AC-JAV-07
layer: PLATFORM
tier: warm
type: lesson
language: java
pack: java_spring_boot
about_concepts: [scheduled-task, distributed-lock, redisson, cluster, spring-boot]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# @Scheduled 定时任务必须加分布式锁，防止集群重复执行

## 教训（Lesson）

Spring Boot 集群部署下，每个实例都会独立触发 `@Scheduled` 定时任务，导致任务被重复执行（如重复扣款、重复发送邮件）。必须加分布式锁保证同一时刻只有一个实例执行。

```java
// ❌ 危险：集群下每个节点都会执行
@Scheduled(cron = "0 0 2 * * ?")     // 每天凌晨2点
public void generateDailyReport() {
    reportService.generate();         // 3个节点 → 生成3份报告！
}
```

```java
// ✅ 正确：Redisson 分布式锁
@Scheduled(cron = "0 0 2 * * ?")
public void generateDailyReport() {
    RLock lock = redissonClient.getLock("scheduled:daily-report");
    boolean acquired = false;
    try {
        acquired = lock.tryLock(0, 300, TimeUnit.SECONDS);  // 不等待，锁超时 5 分钟
        if (!acquired) {
            log.info("另一个节点正在执行日报生成，本节点跳过");
            return;
        }
        reportService.generate();
    } finally {
        if (acquired && lock.isHeldByCurrentThread()) {
            lock.unlock();
        }
    }
}
```

## 轻量替代方案（无 Redis）

```java
// ShedLock：基于 DB 的轻量分布式锁（无需 Redis）
@Scheduled(cron = "0 0 2 * * ?")
@SchedulerLock(name = "daily-report", lockAtMostFor = "5m", lockAtLeastFor = "1m")
public void generateDailyReport() {
    reportService.generate();
}
```

## 参考

- Redisson 文档：[Distributed Lock](https://github.com/redisson/redisson/wiki/8.-Distributed-locks-and-synchronizers)
- ShedLock：https://github.com/lukas-krecan/ShedLock
