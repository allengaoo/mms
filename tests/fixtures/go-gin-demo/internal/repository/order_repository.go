package repository

import (
	"context"

	"gorm.io/gorm"
	"github.com/example/go-gin-demo/internal/domain"
)

// OrderRepository 订单持久化接口（依赖倒置）
type OrderRepository interface {
	FindByID(ctx context.Context, id uint) (*domain.Order, error)
	FindByUserID(ctx context.Context, userID uint, page, size int) ([]*domain.Order, int64, error)
	Save(ctx context.Context, order *domain.Order) error
	Update(ctx context.Context, order *domain.Order) error
}

// gormOrderRepository GORM 实现
type gormOrderRepository struct {
	db *gorm.DB
}

// NewOrderRepository 构造函数
func NewOrderRepository(db *gorm.DB) OrderRepository {
	return &gormOrderRepository{db: db}
}

func (r *gormOrderRepository) FindByID(ctx context.Context, id uint) (*domain.Order, error) {
	var order domain.Order
	if err := r.db.WithContext(ctx).Preload("Items").First(&order, id).Error; err != nil {
		return nil, err
	}
	return &order, nil
}

func (r *gormOrderRepository) FindByUserID(ctx context.Context, userID uint, page, size int) ([]*domain.Order, int64, error) {
	var orders []*domain.Order
	var total int64
	offset := (page - 1) * size
	db := r.db.WithContext(ctx).Where("user_id = ?", userID)
	if err := db.Count(&total).Error; err != nil {
		return nil, 0, err
	}
	if err := db.Offset(offset).Limit(size).Find(&orders).Error; err != nil {
		return nil, 0, err
	}
	return orders, total, nil
}

func (r *gormOrderRepository) Save(ctx context.Context, order *domain.Order) error {
	return r.db.WithContext(ctx).Create(order).Error
}

func (r *gormOrderRepository) Update(ctx context.Context, order *domain.Order) error {
	return r.db.WithContext(ctx).Save(order).Error
}
