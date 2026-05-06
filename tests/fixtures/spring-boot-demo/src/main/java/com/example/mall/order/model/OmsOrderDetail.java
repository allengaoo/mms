package com.example.mall.order.model;

import jakarta.persistence.*;
import lombok.Data;
import java.math.BigDecimal;

/**
 * 订单详情实体（包含商品快照信息）
 */
@Data
@Entity
@Table(name = "oms_order_detail")
public class OmsOrderDetail {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 订单 ID */
    private Long orderId;

    /** 商品 ID */
    private Long productId;

    /** 商品名称（下单时快照） */
    private String productName;

    /** 商品主图（下单时快照） */
    private String productPic;

    /** 商品单价（下单时快照） */
    private BigDecimal productPrice;

    /** 购买数量 */
    private Integer productQuantity;
}
