package com.example.mall.order.controller;

import com.example.mall.order.dto.CreateOrderRequest;
import com.example.mall.order.dto.OrderDetailResponse;
import com.example.mall.order.model.OmsOrder;
import com.example.mall.order.service.OmsOrderService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.List;

/**
 * 订单 REST 控制器
 */
@RestController
@RequestMapping("/api/orders")
@RequiredArgsConstructor
public class OmsOrderController {

    private final OmsOrderService orderService;

    @PostMapping
    public ResponseEntity<OmsOrder> create(@RequestBody CreateOrderRequest request) {
        return ResponseEntity.ok(orderService.createOrder(request));
    }

    @GetMapping("/{id}")
    public ResponseEntity<OrderDetailResponse> detail(@PathVariable Long id) {
        return ResponseEntity.ok(orderService.getOrderDetail(id));
    }

    @GetMapping("/member/{memberId}")
    public ResponseEntity<List<OmsOrder>> listByMember(@PathVariable Long memberId) {
        return ResponseEntity.ok(orderService.listByMember(memberId));
    }
}
