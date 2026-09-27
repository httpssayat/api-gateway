from locust import HttpUser, constant_pacing, task


class GatewayUser(HttpUser):
    """
    Нагрузочный пользователь

    constant_pacing(1.0) даёт примерно одну итерацию в секунду.
    При 300 пользователях получаем приблизительно 300 RPS.
    """

    wait_time = constant_pacing(1.0)

    @task(1)
    def users_request(self):
        """
        Запрос к users.
        """
        self.client.get("/api/users/me", name="/api/users")

    @task(1)
    def orders_request(self):
        """
        Запрос к orders

        Используем POST, чтобы проверить неидемпотентный метод.
        """
        self.client.post(
            "/api/orders",
            json={"item": "load-test"},
            name="/api/orders",
        )

    @task(1)
    def payments_request(self):
        """
        Запрос к payments
        """
        self.client.get("/api/payments/status", name="/api/payments")