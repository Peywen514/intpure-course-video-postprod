# fonts/ 字幕燒錄用字型

`NotoSansTC-Bold.otf` 是 Google Noto CJK 官方 release（`googlefonts/noto-cjk` Sans2.004）
裡的**靜態粗體版本**，授權見 `LICENSES/OFL-NotoSansTC.txt`（SIL Open Font License 1.1，
可自由商用/修改/散布）。

## 為什麼是這個檔案、不是系統安裝的可變字型

思源黑體（Noto Sans TC）官方主要以「可變字型」（Variable Font，一個檔案含所有粗細）散布，
Windows 系統若有裝這個字型，通常裝的就是可變字型版本。但實測發現：ffmpeg 用 libass 燒字幕
時，在 Windows 上比對可變字型的粗細會選錯——要求粗體（Bold）卻選到最細的 Thin，導致「網頁
編輯器預覽是粗體、實際輸出影片變成細體」的落差（瀏覽器自己的字型比對邏輯處理可變字型比較
準，沒有這個問題）。

改用這份單一粗細的**靜態**字型檔可以完全避開這個問題，而且：
- 不用依賴使用者電腦上「剛好有沒有裝 Noto Sans TC」
- Windows / Mac / Linux 行為一致，不用個別排查各平台的可變字型比對差異
- `lib/pipeline.py` 的 `stage_captions` 燒字幕時用 `fontsdir=` 指到這個資料夾，不需要
  另外安裝到系統字型目錄

## 其他集合

只包了 `Bold`——`config.CAPTION_STYLE` 的 `Bold: -1` 是這個專案唯一用到的字重。如果之後
需要其他粗細，去 [googlefonts/noto-cjk 的 Release 頁面](https://github.com/googlefonts/noto-cjk/releases)
下載 `19_NotoSansTC.zip`，裡面有 Thin/Light/DemiLight/Regular/Medium/Bold/Black 全部靜態版本。
