"""FSM states for interactive flows."""

from aiogram.fsm.state import State, StatesGroup


class ChatStates(StatesGroup):
    ai = State()
    music = State()
    image = State()


class AdminStates(StatesGroup):
    broadcast = State()
    user_lookup = State()
