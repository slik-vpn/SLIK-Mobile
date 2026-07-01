import { bot } from './bot/index.js';
import { prisma } from './database/prisma.js';

const shutdown = async (signal: string) => {
  console.log(`Received ${signal}. Stopping bot...`);
  bot.stop(signal);
  await prisma.$disconnect();
  process.exit(0);
};

process.once('SIGINT', () => void shutdown('SIGINT'));
process.once('SIGTERM', () => void shutdown('SIGTERM'));

await bot.launch();
console.log('SLIK Place AI Manager bot started.');
