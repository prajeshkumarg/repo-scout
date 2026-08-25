def configure(
    option_one: int = 1,
    option_two: str = "two",
    option_three: float = 3.0,
    option_four: bool = False,
    option_five: int = 5,
    option_six: str = "six",
    option_seven: float = 7.0,
    option_eight: bool = True,
    option_nine: int = 9,
    option_ten: str = "ten",
    option_eleven: float = 11.0,
    option_twelve: bool = False,
) -> None:
    first = option_one + option_five
    second = option_three + option_seven
    third = first * second
    if option_four and option_eight:
        third += 1
    return third
