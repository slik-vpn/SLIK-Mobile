import type { Prisma } from '@prisma/client';
import { EventLevel } from '@prisma/client';
import { prisma } from '../../database/prisma.js';

type Metadata = Prisma.InputJsonValue;

const writeLog = (level: EventLevel, type: string, message: string, metadata?: Metadata) => {
  return prisma.eventLog.create({
    data: {
      level,
      type,
      message,
      metadata: metadata ?? undefined,
    },
  });
};

export const eventLogService = {
  logInfo: (type: string, message: string, metadata?: Metadata) =>
    writeLog(EventLevel.INFO, type, message, metadata),
  logWarning: (type: string, message: string, metadata?: Metadata) =>
    writeLog(EventLevel.WARNING, type, message, metadata),
  logAlert: (type: string, message: string, metadata?: Metadata) =>
    writeLog(EventLevel.ALERT, type, message, metadata),
  logFinance: (type: string, message: string, metadata?: Metadata) =>
    writeLog(EventLevel.FINANCE, type, message, metadata),
};
