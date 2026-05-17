# 九萬畝 自動挖地腳本 使用說明

> ⚠️ 多數遊戲服務條款禁止使用自動化工具,可能導致帳號被封。請只在你自己的帳號、
> 並已確認不違反條款的前提下使用,風險自負。本工具僅供學習與技術研究。

## 它怎麼運作

《九萬畝》是原生手機 App、像素風遊戲畫面(單一 canvas),抓不到 UI 元素,
所以無法用瀏覽器/Appium 那種方式。本腳本的做法是業界對這類遊戲最通用的方案:

```
ADB 截圖  →  OpenCV 模板比對找按鈕  →  ADB 模擬點擊  →  等待  →  重複
```

跟「模擬點擊」是一樣的邏輯,只是點擊對象從瀏覽器換成模擬器的 Android 畫面。

## 一、環境準備

1. **安裝 Android 模擬器**:LDPlayer(雷電)/ BlueStacks / 夜神 Nox 擇一,
   在裡面安裝並登入《九萬畝》,過完新手教學、確定可以手動挖地。
2. **安裝 ADB**(Android Platform Tools),確認終端機輸入 `adb version` 有反應。
3. **安裝 Python 3.10+ 與套件**:
   ```
   pip install -r requirements.txt
   ```
4. **開啟模擬器的 ADB 偵錯**(多數模擬器設定裡有「ADB 偵錯/Root」開關)。

## 二、設定 ADB 連線

打開 `mining_config.yaml`,把 `adb.serial` 改成你模擬器的位址。常見預設:

| 模擬器 | ADB 位址 |
|--------|----------|
| LDPlayer 雷電 | `127.0.0.1:5555`(第 2 個實例 `5557`,以此類推) |
| BlueStacks | `127.0.0.1:5555` |
| 夜神 Nox | `127.0.0.1:62001` |
| MEmu 逍遙 | `127.0.0.1:21503` |

測試連線並存一張截圖:

```
python auto_mining.py check
```

成功會印出解析度並產生 `screen_check.png`。失敗請檢查模擬器有沒有開、ADB 埠對不對。

## 三、製作模板圖片(最關鍵的一步)

1. 在遊戲裡走一次完整的「挖一塊地」流程,每個關鍵畫面都用 `python auto_mining.py check -o 步驟名.png` 截圖。
2. 用任何看圖/繪圖軟體,把每個**按鈕**裁切出來(貼緊邊界、**不要**包含會變動的數字或背景),
   存成 png 放進 `templates/`,檔名對應 `mining_config.yaml` 裡的 `template` 欄位。
   - 預設需要:`btn_world_map.png` `btn_search.png` `btn_search_go.png`
     `tile_resource.png` `btn_attack.png` `btn_select_troop.png` `btn_march_confirm.png`
3. 模板必須跟執行時**同一解析度**截取(模擬器解析度固定就沒問題)。

## 四、調整流程

`mining_config.yaml` 的 `sequence` 是「挖一塊地」的步驟,從上到下執行,每輪重複。
範本是常見 SLG 流程,請依《九萬畝》實際 UI **增刪/排序**步驟。可用 action:

- `tap_template`:找模板並點中心(可加 `offset_x/offset_y` 點旁邊一點)
- `wait_template`:等某畫面出現才繼續(不點擊),適合等讀取
- `tap`:點固定座標 `x,y`
- `swipe`:滑動(拖地圖用)
- `wait`:等待固定或 `[min,max]` 隨機秒(行軍時間用)
- `back`:按返回鍵(收尾回主畫面)

共用參數:`threshold`(信心門檻,誤判多就調高)、`timeout`、
`optional`(找不到就跳過不算失敗)、`after_delay`(步驟後延遲,可給 `[min,max]`)。

## 五、試跑與正式跑

先用 **dry-run** 驗證模板抓不抓得到(只辨識、不點擊):

```
python auto_mining.py run --dry-run --max-cycles 1
```

看 log 每步是不是都「找到 xxx 信心=0.9x」。都 OK 再正式跑:

```
python auto_mining.py run                 # 依設定檔 loop_count
python auto_mining.py run --max-cycles 5  # 只跑 5 塊地測試
```

`Ctrl+C` 會在目前步驟結束後安全停止。執行記錄在 `auto_mining.log`,
找不到模板時的截圖會存到 `debug/` 方便你比對調整。

## 常見問題

- **一直「逾時找不到模板」**:模板裁太大/含背景、解析度不一致、或門檻太高 →
  重新裁緊一點、確認同解析度、`default_threshold` 降到 0.8 試試。
- **點到錯位置**:模板比對到相似圖案 → 裁更有辨識度的區域或調高 threshold。
- **行軍還沒結束就進下一輪**:把 `wait` 秒數加長,或改用 `wait_template` 等部隊閒置圖示。
- **多開**:每個模擬器實例用不同 ADB 埠,複製一份 config 各自指定 `serial` 分開跑。
