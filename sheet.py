import os

import gspread


class Sheet:

    def __init__(self) -> None:

        account = gspread.service_account( filename=os.path.join(os.path.dirname(__file__), "google-credentials.json"))
        self.sheet = account.open_by_key(os.getenv("GOOGLE_SHEET_ID"))

    def get_statistics_by_categories(self) -> dict:
        main_sheet = self.sheet.worksheet("Main")
        data = main_sheet.batch_get(["J11:K23"])
        result = []
        sum = 0
        for i in range(len(data[0])):
            if data[0][i] == []:
                continue
            result.append(tuple((data[0][i][0], data[0][i][1])))
            sum += float(data[0][i][1])
        result.append(tuple(("🧾 Итого", str(sum))))
        return result

    def get_categories(self) -> list:
        pref_sheet = self.sheet.worksheet("Preferences")
        data = pref_sheet.batch_get(["B4:B43"])

        
        categories = []
        for i in range(len(data[0])):
            if data[0][i] == []:
                continue
            categories.append(data[0][i][0])

        return categories


    def add_transaction(self, data: list):
        transactions = self.sheet.worksheet("Transactions")
        transactions.insert_row(data, index=2, value_input_option="USER_ENTERED")
        return
        """Вставляет новую строку с данными о транзакции в
        список транзакций в Google Sheet.

        Args:
            data (list): данные для вставки в лист пользователя.
        """

        
        
        outcome_tran = [data[0], "", "Transfer", data[1], data[2]]
        income_tran = [data[0], "", "Transfer", data[3], data[4]]

        
        transactions = self.sheet.worksheet("Transactions")
        transactions.insert_rows(
            [income_tran, outcome_tran], row=2, value_input_option="USER_ENTERED"
        )
        return

    def delete_last_transaction(self):
        transactions = self.sheet.worksheet("Transactions")
        transactions.delete_row(2)