package main

import (
	"log"

	"github.com/gin-gonic/gin"
	"github.com/example/go-gin-demo/internal/config"
	"github.com/example/go-gin-demo/internal/handler"
	"github.com/example/go-gin-demo/internal/middleware"
	"github.com/example/go-gin-demo/internal/repository"
	"github.com/example/go-gin-demo/internal/service"
)

func main() {
	cfg := config.Load()

	db, err := config.InitDB(cfg.DSN)
	if err != nil {
		log.Fatalf("failed to connect database: %v", err)
	}

	repo := repository.NewOrderRepository(db)
	svc := service.NewOrderService(repo)
	h := handler.NewOrderHandler(svc)

	r := gin.Default()
	r.Use(middleware.Auth())
	r.Use(middleware.RequestLogger())

	api := r.Group("/api/v1")
	{
		api.GET("/orders", h.ListOrders)
		api.GET("/orders/:id", h.GetOrder)
		api.POST("/orders", h.CreateOrder)
		api.PUT("/orders/:id/cancel", h.CancelOrder)
	}

	log.Fatal(r.Run(cfg.Addr))
}
