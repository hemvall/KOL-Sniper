# Simple setup guide

This file explains, in a very simple way, how to fill every value needed for the sniper.

## 1. Create a .env file
Copy the example file:

```bash
copy .env.example .env
```

Then open the new file named .env and fill the values.

## 2. Telegram values
You need a Telegram account and a Telegram app API key.

### TG_API_ID
- Go to: https://my.telegram.org/apps
- Log in with your Telegram account
- Create an app if needed
- Copy the value called App api id
- Paste it into TG_API_ID

### TG_API_HASH
- On the same page at https://my.telegram.org/apps
- Copy the value called App api hash
- Paste it into TG_API_HASH

### TG_CHANNELS
- Put the Telegram channel names or links you want the bot to watch
- Example:
  - @mychannel
  - https://t.me/mychannel
- If you have more than one, separate them with commas

Example:
```env
TG_CHANNELS=@channel1,@channel2
```

## 3. Wallet value
### SOL_PRIVATE_KEY
- This is your Solana wallet private key
- Use a burner wallet, not your main wallet
- Paste the private key in base58 format
- Example format:
```env
SOL_PRIVATE_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## 4. RPC URL
### SOL_RPC_URL
- This is the Solana node URL used to send transactions
- You can leave the default value if you want:
```env
SOL_RPC_URL=https://api.mainnet-beta.solana.com
```

## 5. Buy settings
### BUY_SOL
- This is how much SOL to spend for each buy
- Example:
```env
BUY_SOL=0.5
```

### SLIPPAGE
- This controls how much slippage you allow
- Example:
```env
SLIPPAGE=15
```

### PRIORITY_FEE
- This helps your transaction get picked faster
- Example:
```env
PRIORITY_FEE=0.001
```

### POOL
- Leave it as default unless you know what you are doing
```env
POOL=auto
```

## 6. Auto sell settings
### AUTOSELL
- Set to true if you want the bot to auto sell after a buy
```env
AUTOSELL=false
```

### TP_MULT
- Take profit multiplier
```env
TP_MULT=2.0
```

### SL_MULT
- Stop loss multiplier
```env
SL_MULT=0.5
```

### PUMPPORTAL_API_KEY
- This is optional
- It is only needed if you want the auto-sell feature to work
- Get it from PumpPortal if you use that feature

## 7. Run the sniper
After filling the .env file, install dependencies and start the bot:

```bash
pip install -r requirements.txt
python sniper.py
```

## 8. Important safety notes
- Use a burner wallet
- Do not use funds you cannot afford to lose
- Keep your private key safe
- Use a secondary Telegram account if possible
