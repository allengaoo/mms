import { Injectable, NotFoundException } from '@nestjs/common';
import { OrdersRepository } from '../repositories/orders.repository';
import { OrderEntity } from '../entities/order.entity';

export interface CreateOrderParams {
  userId: string;
  items: Array<{ productId: string; quantity: number; price: number }>;
}

@Injectable()
export class OrdersService {
  constructor(private readonly ordersRepository: OrdersRepository) {}

  async createOrder(params: CreateOrderParams): Promise<OrderEntity> {
    const totalAmount = params.items.reduce(
      (sum, item) => sum + item.price * item.quantity,
      0,
    );
    const order = new OrderEntity();
    order.userId = params.userId;
    order.items = params.items;
    order.totalAmount = totalAmount;
    order.status = 'pending';
    return this.ordersRepository.save(order);
  }

  async getUserOrders(userId: string): Promise<OrderEntity[]> {
    return this.ordersRepository.findByUserId(userId);
  }

  async cancelOrder(orderId: string, userId: string): Promise<OrderEntity> {
    const order = await this.ordersRepository.findOne(orderId);
    if (!order) {
      throw new NotFoundException(`Order ${orderId} not found`);
    }
    if (order.userId !== userId) {
      throw new Error('Unauthorized');
    }
    order.status = 'cancelled';
    return this.ordersRepository.save(order);
  }
}
