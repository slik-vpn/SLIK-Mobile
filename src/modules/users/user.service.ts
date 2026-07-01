import type { User as TelegramUser } from 'telegraf/types';
import { Role, UserStatus } from '@prisma/client';
import { env } from '../../config/env.js';
import { prisma } from '../../database/prisma.js';
import { eventLogService } from '../event-log/event-log.service.js';

const toTelegramId = (id: number) => String(id);

export const userService = {
  async upsertFromTelegram(from: TelegramUser) {
    const telegramId = toTelegramId(from.id);
    const isOwner = telegramId === env.ownerTelegramId;

    const user = await prisma.user.upsert({
      where: { telegramId },
      create: {
        telegramId,
        username: from.username,
        firstName: from.first_name,
        lastName: from.last_name,
        role: isOwner ? Role.OWNER : Role.EMPLOYEE,
        status: isOwner ? UserStatus.ACTIVE : UserStatus.PENDING,
      },
      update: {
        username: from.username,
        firstName: from.first_name,
        lastName: from.last_name,
        ...(isOwner ? { role: Role.OWNER, status: UserStatus.ACTIVE } : {}),
      },
    });

    await eventLogService.logInfo('user.start', 'User opened the bot', {
      telegramId,
      role: user.role,
      status: user.status,
    });

    return user;
  },

  findByTelegramId(telegramId: number) {
    return prisma.user.findUnique({ where: { telegramId: toTelegramId(telegramId) } });
  },
};
