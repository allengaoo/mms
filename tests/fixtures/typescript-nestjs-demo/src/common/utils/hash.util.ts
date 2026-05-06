import * as crypto from 'crypto';

export class HashUtil {
  static sha256(input: string): string {
    return crypto.createHash('sha256').update(input).digest('hex');
  }

  static md5(input: string): string {
    return crypto.createHash('md5').update(input).digest('hex');
  }

  static isMatch(plain: string, hash: string): boolean {
    return HashUtil.sha256(plain) === hash;
  }
}
