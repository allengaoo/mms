package com.example.mall.order.dto;

import lombok.Data;
import java.math.BigDecimal;

@Data
public class CreateOrderRequest {
    private Long memberId;
    private BigDecimal totalAmount;
    private String receiverName;
    private String receiverDetailAddress;
}
