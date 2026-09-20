import request from "./index";
export const getMe = async()=>request.get('/auth/me')
