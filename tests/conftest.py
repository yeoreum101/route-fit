import os

# 테스트는 네트워크·모델 없이 돈다.
os.environ["ROUTEFIT_LLM"] = "off"
os.environ["ROUTEFIT_EMBEDDER"] = "hashing"
