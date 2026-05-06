package config

import (
	"os"

	"gorm.io/driver/mysql"
	"gorm.io/gorm"
)

// Config 应用配置
type Config struct {
	Addr string
	DSN  string
}

// Load 从环境变量加载配置
func Load() *Config {
	return &Config{
		Addr: getEnv("SERVER_ADDR", ":8080"),
		DSN:  getEnv("DATABASE_DSN", "root:password@tcp(localhost:3306)/orders?parseTime=true"),
	}
}

// InitDB 初始化数据库连接
func InitDB(dsn string) (*gorm.DB, error) {
	return gorm.Open(mysql.Open(dsn), &gorm.Config{})
}

func getEnv(key, defaultVal string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultVal
}
