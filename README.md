# binance-auto-trade

Bot giao dịch tự động **Binance Spot** (chỉ mua, không margin/đòn bẩy/short), Python thuần, **không cần cài thư viện**. Pipeline lấy ý tưởng từ [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill): scanner → sizing → risk → broker, mặc định chạy paper.

> **Không phải lời khuyên tài chính.** Phần lớn người giao dịch ngắn hạn bị lỗ. Backtest không đảm bảo tương lai. Code mới được kiểm thử offline (unit test), **chưa** chạy với tiền thật. Hãy chạy `paper`, rồi `testnet` thật lâu trước khi nghĩ đến `live`.

## Ba chế độ

| mode | làm gì | tiền |
|------|--------|------|
| `paper` (mặc định) | Mô phỏng khớp lệnh trên dữ liệu thật của Binance, không gửi lệnh | không |
| `testnet` | Gửi lệnh lên [Binance Spot Testnet](https://testnet.binance.vision) | tiền giả |
| `live` | Gửi lệnh lên Binance | **tiền thật** |

`live` bị chặn trừ khi đặt `BINANCE_LIVE_CONFIRM=I_ACCEPT_THE_RISK`, và mặc định còn hỏi `yes` trước mỗi lệnh (`require_confirm`).

## Chiến lược (mẫu, để bạn chỉnh)

Breakout theo xu hướng, chỉ long, tính trên nến **đã đóng**: giá đóng cửa vượt đỉnh N nến trước; EMA20 > EMA50 và giá trên EMA50; RSI trong `rsi_min..rsi_max`; volume ≥ `volume_mult` × trung bình. Stop = `atr_stop_mult` × ATR dưới giá vào, target = `reward_risk` × rủi ro. Đây không phải "công thức kiếm tiền": hãy backtest trước.

## Lớp bảo vệ

- **Sizing**: lỗ tại stop (đã tính phí) ≤ `max_loss_per_trade_usd`, ≤ `max_position_pct`% vốn, ≤ số dư
- **Risk check** (PASS/BLOCK kèm lý do): giới hạn lỗ/ngày, số lệnh/ngày, số vị thế mở, trùng symbol, reward/risk tối thiểu, khoảng cách stop hợp lý
- **Thoát lệnh nằm sẵn trên sàn**: mua market rồi đặt OCO (take-profit + stop-loss). Đặt OCO thất bại thì bán ngay, không bao giờ ở trong lệnh mà không có stop
- **Kill switch**: `python3 -m binancebot halt` tạo file `KILL`, bot ngừng vào lệnh mới (vẫn quản lý lệnh đang mở)
- Mỗi nến đóng chỉ ra một quyết định; API key chỉ đọc từ biến môi trường

## Chạy

Cần Python 3.8+.

```bash
cp config.example.json config.json            # config.json bị .gitignore
python3 -m unittest discover -s tests -v      # test offline

python3 -m binancebot scan                    # xem setup hiện tại, không đặt lệnh
python3 -m binancebot backtest --symbol BTCUSDT --candles 3000
python3 -m binancebot run                     # paper, vòng lặp (--once: một vòng)
python3 -m binancebot status
python3 -m binancebot halt | resume
```

**Testnet**: tạo key tại https://testnet.binance.vision, đặt `"mode": "testnet"`, rồi `export BINANCE_API_KEY=... BINANCE_API_SECRET=...` và `run`.

**Live**: chỉ sau nhiều tuần paper/testnet ổn định. Dùng API key riêng, **chỉ bật Spot Trading, tắt Withdrawals**, giới hạn theo IP, giữ `max_loss_per_trade_usd` nhỏ, vốn bạn sẵn sàng mất hoàn toàn. Nếu `api.binance.com` bị chặn ở khu vực của bạn, đặt `base_url` trong config.

## Giới hạn cần biết

- Phí mặc định giả định 0.1%/chiều (`fee_pct`); PnL ở testnet/live là ước tính, hãy đối chiếu lịch sử giao dịch trên Binance
- Stop-limit có thể khớp xấu hơn giá stop khi thị trường gap
- Paper dùng nến 1 phút để kiểm tra stop/target; nếu một nến chạm cả hai thì tính là chạm stop trước
- Backtest vào lệnh ở giá mở nến kế tiếp và không mô phỏng độ sâu sổ lệnh
- Phần gửi lệnh (OCO, đồng bộ lệnh) chưa được kiểm thử với sàn thật: thử trên testnet trước
