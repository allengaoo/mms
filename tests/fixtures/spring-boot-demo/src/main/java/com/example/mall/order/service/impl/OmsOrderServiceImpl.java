package com.example.mall.order.service.impl;

import com.example.mall.order.dto.CreateOrderRequest;
import com.example.mall.order.dto.OrderDetailResponse;
import com.example.mall.order.model.OmsOrder;
import com.example.mall.order.model.OmsOrderDetail;
import com.example.mall.order.repository.OmsOrderRepository;
import com.example.mall.order.service.OmsOrderService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

/**
 * 订单服务实现
 */
@Service
@RequiredArgsConstructor
public class OmsOrderServiceImpl implements OmsOrderService {

    private final OmsOrderRepository orderRepository;

    @Override
    @Transactional
    public OmsOrder createOrder(CreateOrderRequest request) {
        OmsOrder order = new OmsOrder();
        order.setMemberId(request.getMemberId());
        order.setOrderSn(UUID.randomUUID().toString().replace("-", ""));
        order.setTotalAmount(request.getTotalAmount());
        order.setPayAmount(request.getTotalAmount());
        order.setStatus(0);
        order.setReceiverName(request.getReceiverName());
        order.setReceiverDetailAddress(request.getReceiverDetailAddress());
        order.setCreateTime(LocalDateTime.now());
        order.setUpdateTime(LocalDateTime.now());
        return orderRepository.save(order);
    }

    @Override
    public OrderDetailResponse getOrderDetail(Long orderId) {
        OmsOrder order = orderRepository.findById(orderId)
            .orElseThrow(() -> new RuntimeException("订单不存在: " + orderId));
        return OrderDetailResponse.from(order);
    }

    @Override
    public List<OmsOrder> listByMember(Long memberId) {
        return orderRepository.findByMemberId(memberId);
    }

    @Override
    @Transactional
    public int closeTimeoutOrders(int timeoutMinutes) {
        return 0;
    }
}
