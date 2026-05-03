package com.example.mall.order.service;

import com.example.mall.order.dto.CreateOrderRequest;
import com.example.mall.order.dto.OrderDetailResponse;
import com.example.mall.order.model.OmsOrder;
import java.util.List;

/**
 * 订单服务接口
 */
public interface OmsOrderService {

    /**
     * 创建订单
     */
    OmsOrder createOrder(CreateOrderRequest request);

    /**
     * 查询订单详情
     */
    OrderDetailResponse getOrderDetail(Long orderId);

    /**
     * 查询会员订单列表
     */
    List<OmsOrder> listByMember(Long memberId);

    /**
     * 关闭超时未支付订单
     */
    int closeTimeoutOrders(int timeout);
}
