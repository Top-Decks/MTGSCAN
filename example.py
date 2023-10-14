# basic usage of mtgscan
# env variables AZURE_VISION_ENDPOINT and AZURE_VISION_KEY must be set

from mtgscan.text import MagicRecognition
from mtgscan.ocr.azure import Azure

azure = Azure()
rec = MagicRecognition(file_all_cards="all_cards.txt",
                       file_keywords="Keywords.json", max_ratio_diff=0.25)
# 中文卡牌
box_texts = azure.image_to_box_texts(
    "https://xqimg.imedao.com/18b2a6cf9b7b81063fdb0127.jpg")
# 英文卡牌
# box_texts = azure.image_to_box_texts(
#     "https://xqimg.imedao.com/18b2a74b44b7c42c3fc7d32d.jpeg")
deck = rec.box_texts_to_deck(box_texts)
for c, k in deck:
    print(k, c)
