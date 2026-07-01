import { Telegraf } from 'telegraf';
import { env } from '../config/env.js';
import { eventLogService } from '../modules/event-log/event-log.service.js';
import { userService } from '../modules/users/user.service.js';
import { formatName } from '../utils/format.js';
import { getMainMenu } from './menu.js';

export const bot = new Telegraf(env.botToken);

bot.start(async (ctx) => {
  if (!ctx.from) {
    await ctx.reply('Не удалось определить Telegram-пользователя.');
    return;
  }

  const user = await userService.upsertFromTelegram(ctx.from);

  if (user.status === 'PENDING') {
    await ctx.reply('Заявка на доступ создана. Доступ ожидает подтверждения владельца.');
    return;
  }

  await ctx.reply(`Добро пожаловать, ${formatName(user.firstName, user.lastName, user.username)}.`, getMainMenu(user.role));
});

bot.command('me', async (ctx) => {
  if (!ctx.from) {
    await ctx.reply('Не удалось определить Telegram-пользователя.');
    return;
  }

  const user = await userService.findByTelegramId(ctx.from.id);

  if (!user) {
    await ctx.reply('Пользователь не найден. Нажмите /start для регистрации.');
    return;
  }

  await ctx.reply([
    `Telegram ID: ${user.telegramId}`,
    `Имя: ${formatName(user.firstName, user.lastName, user.username)}`,
    `Роль: ${user.role}`,
    `Статус: ${user.status}`,
  ].join('\n'));
});

bot.catch(async (error) => {
  const message = error instanceof Error ? error.message : 'Unknown bot error';
  console.error(error);
  await eventLogService.logAlert('bot.error', message);
});
