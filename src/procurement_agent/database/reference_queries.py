PAST_SIX_MONTHS_BY_BUSINESS_UNIT = """
SELECT bu.business_unit_id, bu.name, ROUND(SUM(po.total_amount_usd), 2) AS spend_usd
FROM purchase_orders AS po
JOIN business_units AS bu ON bu.business_unit_id = po.business_unit_id
WHERE po.status IN ('ISSUED', 'CLOSED')
  AND po.order_date BETWEEN '2026-01-01' AND '2026-06-30'
GROUP BY bu.business_unit_id, bu.name
ORDER BY spend_usd DESC
"""

TOP_Q2_IT_SUPPLIERS = """
SELECT s.supplier_id, s.name, ROUND(SUM(po.total_amount_usd), 2) AS spend_usd
FROM purchase_orders AS po
JOIN suppliers AS s ON s.supplier_id = po.supplier_id
JOIN categories AS c ON c.category_id = po.category_id
WHERE po.status IN ('ISSUED', 'CLOSED')
  AND c.category_code = 'IT_SERVICES'
  AND po.order_date BETWEEN '2026-04-01' AND '2026-06-30'
GROUP BY s.supplier_id, s.name
ORDER BY spend_usd DESC
LIMIT 10
"""

SUP_042_H1_SPEND = """
SELECT CASE WHEN order_date <= '2025-06-30' THEN 'H1_2025' ELSE 'H1_2026' END AS period,
       ROUND(SUM(total_amount_usd), 2) AS spend_usd
FROM purchase_orders
WHERE supplier_id = 'SUP-042'
  AND status IN ('ISSUED', 'CLOSED')
  AND ((order_date BETWEEN '2025-01-01' AND '2025-06-30')
       OR (order_date BETWEEN '2026-01-01' AND '2026-06-30'))
GROUP BY period
ORDER BY period
"""

INDIRECT_PARETO = """
WITH supplier_spend AS (
  SELECT po.supplier_id, ROUND(SUM(po.total_amount_usd), 2) AS spend_usd
  FROM purchase_orders AS po
  JOIN categories AS c ON c.category_id = po.category_id
  WHERE po.status IN ('ISSUED', 'CLOSED')
    AND c.procurement_class = 'INDIRECT'
    AND po.order_date BETWEEN '2026-01-01' AND '2026-06-30'
  GROUP BY po.supplier_id
), ranked AS (
  SELECT supplier_id, spend_usd,
         SUM(spend_usd) OVER (ORDER BY spend_usd DESC, supplier_id) AS cumulative_spend,
         SUM(spend_usd) OVER () AS total_spend
  FROM supplier_spend
)
SELECT supplier_id, spend_usd, cumulative_spend, total_spend,
       cumulative_spend / total_spend AS cumulative_share
FROM ranked
ORDER BY spend_usd DESC, supplier_id
"""

OFF_CONTRACT_FACTS = """
SELECT po.po_number, po.contract_reference, po.contract_id, po.contract_evidence_status,
       c.status AS contract_status, c.effective_date, c.expiration_date, c.termination_date,
       c.supplier_id AS contract_supplier_id, c.category_id AS contract_category_id
FROM purchase_orders AS po
LEFT JOIN contracts AS c ON c.contract_id = po.contract_id
WHERE po.po_number IN ('PO-2026-1837', 'PO-2026-1838', 'PO-2026-1839', 'PO-2026-1840', 'PO-2026-1847')
ORDER BY po.po_number
"""

HIGH_VALUE_APPROVAL_FACTS = """
SELECT po.po_number, po.total_amount_usd, po.order_date, po.approval_evidence_status,
       a.approval_type, a.status AS approval_status, a.approver_id, a.approver_role, a.approved_at
FROM purchase_orders AS po
LEFT JOIN approvals AS a ON a.po_number = po.po_number AND a.approval_type = 'PURCHASE'
WHERE po.status IN ('ISSUED', 'CLOSED') AND po.total_amount_usd > 50000
ORDER BY po.po_number, a.approved_at
"""

CANONICAL_PO_FACTS = """
SELECT po.po_number, po.total_amount_usd, po.currency, po.order_date, po.status,
       po.approval_evidence_status, po.contract_evidence_status,
       s.supplier_id, s.name AS supplier_name,
       c.category_id, c.name AS category_name, c.contract_required,
       bu.business_unit_id, bu.name AS business_unit_name,
       po.contract_reference, po.contract_id,
       ct.status AS contract_status, ct.effective_date, ct.expiration_date, ct.termination_date,
       a.approval_type, a.status AS approval_status, a.approver_id, a.approver_role, a.approved_at
FROM purchase_orders AS po
JOIN suppliers AS s ON s.supplier_id = po.supplier_id
JOIN categories AS c ON c.category_id = po.category_id
JOIN business_units AS bu ON bu.business_unit_id = po.business_unit_id
LEFT JOIN contracts AS ct ON ct.contract_id = po.contract_id
LEFT JOIN approvals AS a ON a.po_number = po.po_number
WHERE po.po_number = 'PO-2026-1842'
ORDER BY a.approved_at
"""

SINGLE_SOURCE_FACTS = """
WITH category_spend AS (
  SELECT po.category_id, po.supplier_id, SUM(po.total_amount_usd) AS spend_usd
  FROM purchase_orders AS po
  WHERE po.status IN ('ISSUED', 'CLOSED')
    AND po.order_date BETWEEN '2026-01-01' AND '2026-06-30'
    AND po.category_id = 'CAT-PRO'
  GROUP BY po.category_id, po.supplier_id
), qualified AS (
  SELECT category_id, COUNT(*) AS qualified_supplier_count
  FROM supplier_category_eligibility
  WHERE qualification_status = 'QUALIFIED'
  GROUP BY category_id
), ranked AS (
  SELECT cs.category_id, c.is_critical, cs.supplier_id, cs.spend_usd,
         SUM(cs.spend_usd) OVER (PARTITION BY cs.category_id) AS category_spend_usd,
         1.0 * cs.spend_usd / SUM(cs.spend_usd) OVER (PARTITION BY cs.category_id) AS supplier_spend_share,
         q.qualified_supplier_count
  FROM category_spend AS cs
  JOIN categories AS c ON c.category_id = cs.category_id
  JOIN qualified AS q ON q.category_id = cs.category_id
)
SELECT *
FROM ranked
WHERE supplier_id = 'SUP-017'
"""
