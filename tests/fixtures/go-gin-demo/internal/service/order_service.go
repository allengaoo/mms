package service

import (
	"context"
	"fmt"

	"github.com/example/go-gin-demo/internal/domain"
	"github.com/example/go-gin-demo/internal/repository"
)

// CreateOrderRequest 创建订单请求 DTO
type CreateOrderRequest struct {
	UserID uint
	Items  []OrderItemDTO
}

// OrderItemDTO 订单行 DTO
type OrderItemDTO struct {
	ProductID uint
	Quantity  int
	Price     float64
}

// OrderService 订单应用服务（用例编排）
type OrderService struct {
	repo repository.OrderRepository
}

// NewOrderService 构造函数
func NewOrderService(repo repository.OrderRepository) *OrderService {
	return &OrderService{repo: repo}
}

// ListOrders 分页查询用户订单
func (s *OrderService) ListOrders(ctx context.Context, userID uint, page, size int) ([]*domain.Order, int64, error) {
	if size <= 0 || size > 100 {
		size = 20
	}
	return s.repo.FindByUserID(ctx, userID, page, size)
}

// GetOrder 查询单个订单（验证权限）
func (s *OrderService) GetOrder(ctx context.Context, orderID, userID uint) (*domain.Order, error) {
	order, err := s.repo.FindByID(ctx, orderID)
	if err != nil {
		return nil, err
	}
	if order.UserID != userID {
		return nil, fmt.Errorf("forbidden: order does not belong to user")
	}
	return order, nil
}

// CreateOrder 创建订单（业务用例）
func (s *OrderService) CreateOrder(ctx context.Context, req *CreateOrderRequest) (*domain.Order, error) {
	var total float64
	items := make([]domain.OrderItem, 0, len(req.Items))
	for _, item := range req.Items {
		total += float64(item.Quantity) * item.Price
		items = append(items, domain.OrderItem{
			ProductID: item.ProductID,
			Quantity:  item.Quantity,
			Price:     item.Price,
		})
	}
	order := &domain.Order{
		UserID:     req.UserID,
		Status:     string(domain.StatusPending),
		TotalPrice: total,
		Items:      items,
	}
	if err := s.repo.Save(ctx, order); err != nil {
		return nil, err
	}
	return order, nil
}

// CancelOrder 取消订单（委托领域模型处理状态机）
func (s *OrderService) CancelOrder(ctx context.Context, orderID, userID uint) error {
	order, err := s.GetOrder(ctx, orderID, userID)
	if err != nil {
		return err
	}
	if err := order.Cancel(); err != nil {
		return err
	}
	return s.repo.Update(ctx, order)
}
