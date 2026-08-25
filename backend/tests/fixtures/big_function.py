def process(items):
    result = []
    for item in items:
        value = item.strip()
        if value:
            result.append(value)
        else:
            result.append("empty")
    count = len(result)
    total = 0
    for value in result:
        total += len(value)
    return result, total
