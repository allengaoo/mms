package handler

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/example/go-gin-demo/internal/service"
	"github.com/example/go-gin-demo/pkg/response"
)

// OrderHandler HTTP 适配层（Gin Handler）
type OrderHandler struct {
	svc *service.OrderService
}

// NewOrderHandler 构造函数
func NewOrderHandler(svc *service.OrderService) *OrderHandler {
	return &OrderHandler{svc: svc}
}

// ListOrders GET /api/v1/orders
func (h *OrderHandler) ListOrders(c *gin.Context) {
	userID := c.GetUint("user_id")
	page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	size, _ := strconv.Atoi(c.DefaultQuery("size", "20"))

	orders, total, err := h.svc.ListOrders(c.Request.Context(), userID, page, size)
	if err != nil {
		response.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	response.PageOK(c, orders, total, page, size)
}

// GetOrder GET /api/v1/orders/:id
func (h *OrderHandler) GetOrder(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.Error(c, http.StatusBadRequest, "invalid order id")
		return
	}
	userID := c.GetUint("user_id")

	order, err := h.svc.GetOrder(c.Request.Context(), uint(id), userID)
	if err != nil {
		response.Error(c, http.StatusNotFound, err.Error())
		return
	}
	response.OK(c, order)
}

// CreateOrder POST /api/v1/orders
func (h *OrderHandler) CreateOrder(c *gin.Context) {
	var req service.CreateOrderRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.Error(c, http.StatusBadRequest, err.Error())
		return
	}
	req.UserID = c.GetUint("user_id")

	order, err := h.svc.CreateOrder(c.Request.Context(), &req)
	if err != nil {
		response.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	response.Created(c, order)
}

// CancelOrder PUT /api/v1/orders/:id/cancel
func (h *OrderHandler) CancelOrder(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.Error(c, http.StatusBadRequest, "invalid order id")
		return
	}
	userID := c.GetUint("user_id")

	if err := h.svc.CancelOrder(c.Request.Context(), uint(id), userID); err != nil {
		response.Error(c, http.StatusBadRequest, err.Error())
		return
	}
	response.OK(c, gin.H{"message": "order cancelled"})
}
