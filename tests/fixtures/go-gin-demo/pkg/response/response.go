package response

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// Result 统一响应结构
type Result struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
}

// PageResult 分页响应结构
type PageResult struct {
	Total int64 `json:"total"`
	Page  int   `json:"page"`
	Size  int   `json:"size"`
	Items any   `json:"items"`
}

// OK 成功响应
func OK(c *gin.Context, data any) {
	c.JSON(http.StatusOK, Result{Code: 0, Message: "ok", Data: data})
}

// Created 创建成功
func Created(c *gin.Context, data any) {
	c.JSON(http.StatusCreated, Result{Code: 0, Message: "created", Data: data})
}

// PageOK 分页成功响应
func PageOK(c *gin.Context, items any, total int64, page, size int) {
	c.JSON(http.StatusOK, Result{
		Code:    0,
		Message: "ok",
		Data:    PageResult{Total: total, Page: page, Size: size, Items: items},
	})
}

// Error 错误响应
func Error(c *gin.Context, httpCode int, msg string) {
	c.JSON(httpCode, Result{Code: httpCode, Message: msg})
}
