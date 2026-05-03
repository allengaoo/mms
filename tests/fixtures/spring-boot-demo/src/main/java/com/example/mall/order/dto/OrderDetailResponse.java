package com.example.mall.order.dto;

import com.example.mall.order.model.OmsOrder;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
public class OrderDetailResponse {
    private Long id;
    private String orderSn;
    private Integer status;
    private BigDecimal totalAmount;
    private String receiverName;
    private LocalDateTime createTime;

    public static OrderDetailResponse from(OmsOrder order) {
        OrderDetailResponse resp = new OrderDetailResponse();
        resp.setId(order.getId());
        resp.setOrderSn(order.getOrderSn());
        resp.setStatus(order.getStatus());
        resp.setTotalAmount(order.getTotalAmount());
        resp.setReceiverName(order.getReceiverName());
        resp.setCreateTime(order.getCreateTime());
        return resp;
    }
}
