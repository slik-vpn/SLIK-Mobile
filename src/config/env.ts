import 'dotenv/config';

const requiredEnv = ['BOT_TOKEN', 'OWNER_TELEGRAM_ID', 'DATABASE_URL'] as const;

for (const key of requiredEnv) {
  if (!process.env[key]) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
}

export const env = {
  botToken: process.env.BOT_TOKEN!,
  ownerTelegramId: process.env.OWNER_TELEGRAM_ID!,
  databaseUrl: process.env.DATABASE_URL!,
};
