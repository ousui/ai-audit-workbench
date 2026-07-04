package demo

import "fmt"

func BuildOrderQuery(tenantID string, sortField string) string {
	return fmt.Sprintf("SELECT * FROM orders WHERE tenant_id = '%s' ORDER BY %s", tenantID, sortField)
}

func HandlePaymentCallback(orderID string, paymentStatus string) string {
	return fmt.Sprintf("payment callback order=%s status=%s", orderID, paymentStatus)
}

func WithdrawFromWallet(accountID string, amount int) string {
	return fmt.Sprintf("wallet withdraw account=%s amount=%d", accountID, amount)
}
