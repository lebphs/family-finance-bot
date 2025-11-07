from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from sheet import Sheet

def categories_keyboard() -> ReplyKeyboardMarkup:
    sheet = Sheet()
    categories = sheet.get_categories()
    keyboards = []
    for i in range(0, len(categories), 2):
        if len(categories) - i == 1:
            keyboards.append([KeyboardButton(text=categories[-1])])
            break
        
        keyboards.append([
            KeyboardButton(text=categories[i]), 
            KeyboardButton(text=categories[i + 1])
            ])

    return ReplyKeyboardMarkup(keyboard=keyboards,
        resize_keyboard=True, one_time_keyboard=True)

def main_inlinekeyboard() -> ReplyKeyboardMarkup:
    keyboards = []
    keyboards.append([
        InlineKeyboardButton(text="Отменить операцию", callback_data="delete_last_transaction"),
        InlineKeyboardButton(text="Просмотреть статистику", callback_data="show_statistics") 
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboards,
        resize_keyboard=True, one_time_keyboard=True)

def no_description_keyboard() -> ReplyKeyboardMarkup:
    markup = ReplyKeyboardMarkup( keyboard=[
            [KeyboardButton(text="Без описания")]
        ],
        resize_keyboard=True, one_time_keyboard=True)

    return markup