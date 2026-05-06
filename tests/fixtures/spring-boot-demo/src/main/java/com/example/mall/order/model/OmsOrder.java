package com.example.mall.order.model;

import jakarta.persistence.*;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 订单主表实体
 */
@Data
@Entity
@Table(name = "oms_order")
public class OmsOrder {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 会员 ID */
    private Long memberId;

    /** 订单编号 */
    private String orderSn;

    /** 订单总金额 */
    private BigDecimal totalAmount;

    /** 支付金额 */
    private BigDecimal payAmount;

    /** 订单状态：0→待付款，1→待发货，2→已发货，3→已完成，4→已关闭 */
    private Integer status;

    /** 收货人姓名 */
    private String receiverName;

    /** 收货地址 */
    private String receiverDetailAddress;

    /** 创建时间 */
    private LocalDateTime createTime;

    /** 更新时间 */
    private LocalDateTime updateTime;
}
