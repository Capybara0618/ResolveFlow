"""Public synthetic catalog for the clean local experience; never creates transactions."""

STORES = [
    ("M-1001", "松间数码", "日常工作与聆听的数码用品", "electronics"),
    ("M-1002", "拾光家居", "给生活添一份舒适", "home"),
    ("M-1003", "轻行户外", "轻装出行，享受户外时光", "outdoor"),
]

# name, asset, first price (CNY), optional second price, variants
PRODUCTS = [
    [
        ("无线降噪耳机", "headphones", 329, 349, "黑色", "银色"),
        ("机械键盘", "keyboard", 199, 219, "白色", "深灰色"),
        ("无线鼠标", "mouse", 89, 99, "灰色", "白色"),
        ("蓝牙音箱", "speaker", 159, 179, "黑色", "蓝色"),
        ("桌面充电器", "charger", 69, 89, "单口", "双口"),
        ("办公显示器", "monitor", 699, None, "24英寸", ""),
        ("多口扩展坞", "hub", 129, None, "六合一", ""),
        ("便携充电宝", "powerbank", 149, None, "10000mAh", ""),
        ("笔记本支架", "stand", 79, None, "银色", ""),
        ("桌面摄像头", "webcam", 199, None, "高清款", ""),
    ],
    [
        ("桌面台灯", "lamp", 129, 149, "米白色", "深灰色"),
        ("保温杯", "cup", 89, 99, "银色", "奶白色"),
        ("棉麻靠枕", "pillow", 59, 69, "米色", "绿色"),
        ("编织收纳篮", "basket", 39, 49, "小号", "大号"),
        ("柔软盖毯", "blanket", 129, 159, "米白色", "浅灰色"),
        ("简约挂钟", "clock", 69, None, "白色", ""),
        ("陶瓷花瓶", "vase", 59, None, "米白色", ""),
        ("木质托盘", "tray", 49, None, "原木色", ""),
        ("客厅地毯", "mat", 199, None, "浅灰色", ""),
        ("桌面收纳盒", "basket", 79, None, "三层款", ""),
    ],
    [
        ("轻量双肩包", "backpack", 169, 189, "深蓝色", "橄榄绿"),
        ("双人露营帐篷", "tent", 399, 499, "标准款", "加宽款"),
        ("便携折叠椅", "chair", 129, 149, "黑色", "卡其色"),
        ("瑜伽运动垫", "mat", 79, 99, "6mm", "8mm"),
        ("运动水壶", "bottle", 69, 79, "600ml", "800ml"),
        ("充电露营灯", "lantern", 89, None, "暖光款", ""),
        ("晴雨折叠伞", "umbrella", 59, None, "深蓝色", ""),
        ("防水收纳袋", "bag", 49, None, "10L", ""),
        ("轻量登山杖", "pole", 129, None, "单支款", ""),
        ("户外遮阳帽", "hat", 39, None, "卡其色", ""),
    ],
]


def catalog() -> dict:
    stores, products, skus = [], [], []
    for index, (merchant, name, description, category) in enumerate(STORES, 1):
        stores.append({"store_id": merchant, "name": name, "description": description})
        for number, (title, asset, first, second, variant, other) in enumerate(
            PRODUCTS[index - 1], 1
        ):
            product = f"P-{index}{number:03d}"
            products.append(
                {
                    "product_id": product,
                    "store_id": merchant,
                    "name": title,
                    "description": f"{title}，适合日常使用。请选择合适的规格。",
                    "category": category,
                    "asset_key": asset,
                }
            )
            for slot, (price, choice) in enumerate(
                [(first, variant)] + ([(second, other)] if second else []), 1
            ):
                skus.append(
                    {
                        "sku_id": f"SKU-{index}{number:03d}-{slot:02d}",
                        "product_id": product,
                        "variant": choice,
                        "unit_amount": price * 100,
                        "max_quantity": 10,
                    }
                )
    return {"stores": stores, "products": products, "skus": skus}


def accounts() -> list[dict]:
    rows = [
        {
            "username": "platform",
            "display_name": "平台管理员",
            "role": "PLATFORM_ADMIN",
            "merchant_id": None,
            "buyer_id": None,
        }
    ]
    rows.extend(
        {
            "username": f"buyer{i:02d}",
            "display_name": f"买家{i:02d}",
            "role": "CUSTOMER",
            "merchant_id": None,
            "buyer_id": f"B-{i:04d}",
        }
        for i in range(1, 11)
    )
    for i, (merchant, name, _, _) in enumerate(STORES, 1):
        rows.append(
            {
                "username": f"admin{i:02d}",
                "display_name": f"{name}管理员",
                "role": "MERCHANT_ADMIN",
                "merchant_id": merchant,
                "buyer_id": None,
            }
        )
        rows.extend(
            {
                "username": f"staff{n:02d}",
                "display_name": f"{name}专员{slot}",
                "role": "REVIEWER",
                "merchant_id": merchant,
                "buyer_id": None,
            }
            for slot, n in enumerate((i * 2 - 1, i * 2), 1)
        )
    return rows
