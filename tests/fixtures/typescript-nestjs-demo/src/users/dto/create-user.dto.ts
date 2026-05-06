import { IsEmail, IsString, MinLength } from 'class-validator';

export class CreateUserDto {
  @IsEmail()
  email: string;

  @IsString()
  @MinLength(8)
  password: string;

  @IsString()
  fullName: string;
}

export class UpdateUserDto {
  @IsString()
  fullName?: string;

  @IsString()
  status?: string;
}
