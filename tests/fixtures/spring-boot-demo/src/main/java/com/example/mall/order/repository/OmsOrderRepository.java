package com.example.mall.order.repository;

import com.example.mall.order.model.OmsOrder;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;

/**
 * 订单 JPA Repository
 */
@Repository
public interface OmsOrderRepository extends JpaRepository<OmsOrder, Long> {

    List<OmsOrder> findByMemberId(Long memberId);

    List<OmsOrder> findByStatus(Integer status);
}
