export interface PageResult<T> {
  list: T[];
  total: number;
  page: number;
  pageSize: number;
}
  export interface AxiosResponse<T = any> {
    data: T;
    status: number;
    statusText: string;
    headers: any;
    config: any;
    request?: any;
  }

  export interface ApiResponse<T = unknown> {
    code: number;
    msg?: string;
    data: T|null;
  }
