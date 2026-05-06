import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository, Between } from 'typeorm';
import { OrderEntity } from '../entities/order.entity';

@Injectable()
export class OrdersRepository {
  constructor(
    @InjectRepository(OrderEntity)
    private readonly repo: Repository<OrderEntity>,
  ) {}

  async findByUserId(userId: string): Promise<OrderEntity[]> {
    return this.repo.find({ where: { userId } });
  }

  async findByDateRange(from: Date, to: Date): Promise<OrderEntity[]> {
    return this.repo.find({ where: { createdAt: Between(from, to) } });
  }

  async save(order: OrderEntity): Promise<OrderEntity> {
    return this.repo.save(order);
  }

  async findOne(id: string): Promise<OrderEntity | null> {
    return this.repo.findOne({ where: { id } });
  }
}
