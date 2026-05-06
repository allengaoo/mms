package domain

import "time"

// Order 订单聚合根（领域实体）
type Order struct {
	ID         uint      `gorm:"primaryKey"`
	UserID     uint      `gorm:"not null;index"`
	Status     string    `gorm:"type:varchar(32);default:'pending'"`
	TotalPrice float64   `gorm:"type:decimal(10,2)"`
	CreatedAt  time.Time
	UpdatedAt  time.Time
	Items      []OrderItem `gorm:"foreignKey:OrderID"`
}

// OrderItem 订单行项目（值对象）
type OrderItem struct {
	ID        uint    `gorm:"primaryKey"`
	OrderID   uint    `gorm:"not null;index"`
	ProductID uint    `gorm:"not null"`
	Quantity  int     `gorm:"not null"`
	Price     float64 `gorm:"type:decimal(10,2)"`
}

// OrderStatus 订单状态枚举
type OrderStatus string

const (
	StatusPending   OrderStatus = "pending"
	StatusConfirmed OrderStatus = "confirmed"
	StatusShipped   OrderStatus = "shipped"
	StatusCancelled OrderStatus = "cancelled"
)

// CanCancel 判断订单是否可以取消
func (o *Order) CanCancel() bool {
	return o.Status == string(StatusPending) || o.Status == string(StatusConfirmed)
}

// Cancel 取消订单（领域行为）
func (o *Order) Cancel() error {
	if !o.CanCancel() {
		return ErrOrderCannotCancel
	}
	o.Status = string(StatusCancelled)
	return nil
}

// ErrOrderCannotCancel 订单状态不允许取消
var ErrOrderCannotCancel = &DomainError{Code: "ORDER_CANNOT_CANCEL", Msg: "order cannot be cancelled in current status"}

// DomainError 领域层错误
type DomainError struct {
	Code string
	Msg  string
}

func (e *DomainError) Error() string { return e.Msg }
